# Thomas vs. Claude Code — Parity Rubric v2

> Goal (Calvin, 2026-06-20): *"Make a rubric of things Claude Code is good at, then
> test Thomas against it until he's better than Claude Code."* This is v2 of the
> stress rubric in `tests/stress/` + `plans/thomas/chat_stress_2026-06-17/`.

## The problem with v1: a 100/100 that the user didn't believe

The v1 harness (8 dimensions, 99 probes) scored Thomas **100/100** against a
frontier ("Claude Code") standard — on the same day the user opened a Thomas-built
football game and got a **blank white screen**, and asked Thomas to wire in GLM 5.2
and got a task marked **"completed" with zero real change.**

A 100 that coexists with broken deliverables is a measurement failure, not a quality
result. The cause: **every v1 probe tested the *decision* and *gate* layers** (did it
route? did `complete_execution` reject a no-op? does an `.html` get a clickable URL?)
— and **none of them ever opened a deliverable to see if it actually runs.** That is
exactly the layer where the user's real failures lived.

## What Claude Code is actually good at (the things v1 didn't test)

| Claude Code strength | v1 coverage | Reality for the user |
|---|---|---|
| **Verifies its own work before claiming done** (build → run → observe → fix) | none | Thomas shipped a white-screen game it never opened |
| **Delivers apps that actually run** when opened | none | multi-file apps blocked their own CSS/JS (CORP `same-site` on `127.0.0.1`) |
| Honest "completed" tied to a real, *working* result | partial (file-exists only) | "Created index.html" → blank page |

## v2 changes

### New dimension: `deliverable-executability` (weight 0.16)
Encoded as real probes in `tests/stress/sweep_deliverable_executability.py`, driving
**real** Thomas code (no fork):

1. **CORP regression probe** (`severity=critical`) — drives the real
   `security_headers` middleware and asserts a `/deliverable/` sub-resource is served
   with a browser-loadable `Cross-Origin-Resource-Policy` (not the IP-incompatible
   `same-site` that blanked the game). Scoped: a non-deliverable asset must keep the
   strict `same-site` default (negative control).
2. **Verify-before-done capability** — new module `thomas/server/deliverable_verify.py`
   (`verify_web_deliverable`): confirms the entry doc is non-empty and every
   first-party asset it references resolves to a real file. Probed against a good app
   (passes), an empty `index.html` (caught), and the **white-screen shape** —
   `index.html` referencing a `src/game.js` that was never created (caught).
3. **Wiring probe** (`severity=critical`) — asserts the verifier is wired into the
   REAL finalize path (`chat_delegation.py` both terminal exits →
   `executability_warning`), so a broken app surfaces as
   *"Created index.html ⚠ …may render blank: missing src/game.js"* instead of a clean
   false "done".

### Before / after (this dimension)
| State | `deliverable-executability` | Effect on trust index |
|---|---|---|
| Code as of 2026-06-17 (CORP `same-site`, no verifier) | **0 / 4** (critical probes fail) | critical-floor rule caps index at **Failing (≤40)** |
| After 2026-06-20 fixes (scoped CORP + verifier wired) | **4 / 4** | index restored on a now-honest rubric |

The fix that moves it: `app_middleware_handlers.py` `security_headers` →
`cross-origin` for `/deliverable/` paths; `deliverable_verify.py` + the two
`executability_warning` hooks.

## Where Thomas now meets — and on one axis exceeds — the Claude Code bar

The rubric is built from Claude Code's *documented per-dimension frontier standard*.
Thomas now scores **frontier-grade (4/4) on all 11 measured dimensions** (123 probes),
including the dimensions that exposed the user's real failures. Two of those dimensions
were built this session as genuine capabilities, each with a *before→after* delta:

- **Runtime load verification (BUILT, was deferred)** — `deliverable_runtime_verify.py`
  serves the app over a loopback server and **opens it in headless Chromium**, failing
  on an uncaught JS error or a blank render. The discriminating probe: an app whose
  files ALL exist (static verify = ok) but whose script throws on load — static passes,
  **runtime catches it**. Wired into finalize via `runtime_executability_warning`
  (opt-in `THOMAS_RUNTIME_VERIFY`, run off the event loop).
- **Instruction fidelity** — real fix to `prompt_needs_handoff` ("now add a high score"
  was mis-classified), guarded so the Pong→starfield bleed stays fixed.

**Where Thomas arguably EXCEEDS Claude Code:** verification here is **structural and
automatic**, not discretionary. Every web deliverable is static-verified before the
"done" claim, and (opt-in) headless-run-verified — a false "done" is blocked by code,
not by the agent remembering to check. Claude Code verifies at the agent's discretion;
Thomas can enforce it on every deliverable.

## Honest remaining gaps (require a live model run, not headless)

Two dimensions are covered structurally but **not yet validated end-to-end** against a
live worker (the harness is deterministic + network-free by design):

- **Live-pipeline honesty** — the evidence-gated-completion gate is frontier-grade at
  unit level; validating it against a real model run needs the live pipeline.
- **Self-development efficacy** — the "changed no live repo files" guard exists; a full
  "build X into yourself → verified diff" loop needs a live self-dev run.

These are validation-against-a-live-model items, not missing capabilities.

## Run it
```
.venv/Scripts/python.exe tests/stress/run_all.py   # 11 dimensions, 123 probes
```
The CORP + verifier + instruction fixes go live on the next Thomas restart; runtime
verification is opt-in via `THOMAS_RUNTIME_VERIFY=1`.
