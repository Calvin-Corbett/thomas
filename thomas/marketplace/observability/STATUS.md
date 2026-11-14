# Module: observability

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (real instrumentation, no placeholders)     |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — run store, task ledger, agent presence wired     |
| Has real tests   | partial (focus_scorecard has test file)                 |
| Blocking issues  | run_store.py at exactly 800 lines (right at limit)     |

## What This Is

Internal observability and instrumentation for Thomas. 3,669 lines across
15 files. No placeholders — all real code. Tracks runs, tasks, file audits,
LOC changes, module health, onboarding outcomes, focus scorecards, journals,
event recording, auto-instrumentation, and PII redaction in telemetry.

## What Actually Works

- `run_store.py` (800 lines) — Stores and queries agent run history. Real,
  at the exact line limit.
- `run_store_replay.py` (108 lines) — Replay stored runs. Real.
- `run_db.py` (97 lines) — Run database layer. Real.
- `task_ledger.py` (494 lines) — Task tracking ledger. Real.
- `loc_tracker.py` (311 lines) — Lines of code change tracking. Real.
- `file_audit.py` (307 lines) — File change auditing. Real.
- `module_audit.py` (230 lines) — Module health auditing. Real.
- `focus_scorecard.py` (208 lines) — Focus/quality scorecards. Real.
- `journal.py` (206 lines) — Observability journal. Real.
- `event_recorder.py` (180 lines) — Event recording pipeline. Real.
- `auto_instrument.py` (151 lines) — Auto-instrumentation hooks. Real.
- `redaction.py` (131 lines) — PII redaction in telemetry data. Real.
- `onboarding_outcomes.py` (288 lines) — Onboarding tracking. Real.
- `onboarding_outcomes_gate.py` (157 lines) — Onboarding gates. Real.

This is one of the cleanest modules in the project — no placeholders,
reasonable file sizes, clear purpose for each file.

## Architecture Notes

Observability feeds into:
- The server's `/api/agents/activity` endpoint (agent presence, added 0.14.37)
- The testing suite reports
- The REPL status displays
- Mission control dashboards

The run_store is the backbone — it records what Thomas did, when, and what
happened. The task_ledger tracks ongoing work. The event_recorder captures
discrete events for replay and debugging.

## Known Gaps

- run_store.py at exactly 800 lines (any addition needs a split)
- No distributed tracing (single-process only)
- No external observability export (no OpenTelemetry, Datadog, etc.)
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `redaction.py` — PII protection in telemetry. Security-sensitive.
- `run_store.py` — Core data store. At line limit — next change requires split.
