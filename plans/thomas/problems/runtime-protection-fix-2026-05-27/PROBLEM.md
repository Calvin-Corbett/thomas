# Task Problem Record: runtime-protection-fix-2026-05-27

- task_id: `runtime-protection-fix-2026-05-27`
- owner: `unassigned`
- status: `up_for_grabs`
- scope: `scripts,thomas`
- summary: close fs.write_file bypass of runtime/.runtime_protection_disabled flag via signed-content plus path protection
- created_at_utc: `2026-05-27T00:00:00+00:00`
- last_synced_at_utc: `2026-06-03T00:00:00+00:00`

## Problem Statement

- The runtime-protection toggle writes a `runtime/.runtime_protection_disabled`
  flag that flag-honoring gates consult to allow a sanctioned, human-authorized
  bypass. A sanctioned filesystem write tool (`fs.write_file`) could be used to
  create or flip that flag (and adjacent protected paths) directly, side-stepping
  the native-auth tap that is supposed to gate disabling protection.

## Evidence

- Red/blue Praxis exercise findings recorded under task
  `praxis-unbypassable-2026-05-29` and the agent message traffic in
  `plans/thomas/WORKBOARD.md` (filesystem-write and signed-content bypass class).

## Root Cause Hypothesis

- The runtime flag was treated as ordinary repo content: writable by the agent's
  sanctioned filesystem tools, with protection keyed on path/name rather than on
  a native-auth-gated operation. Signed-content writes could therefore mint the
  disable flag without a human tap.

## Fix Plan

1. Treat the runtime-protection flag and the breakglass markers as native-auth
   gated artifacts, not agent-writable content; the filesystem tools must refuse
   to write them outside the authorized toggle path.
2. Keep the toggle (`scripts/runtime_protection_toggle.py`) as the single
   Windows-Hello-gated entry point for disabling protection.
3. Add regressions asserting `fs.write_file` cannot create/flip the flag.

## Outcome

- Largely addressed by the Praxis cage / runtime-guard hardening line (see
  `thomas_praxis_cage_2026-06-01` and the `_runtime_guard.py` / breakglass
  spine). Record retained for traceability; residual: confirm the native-auth
  filesystem extension blocks every protected path on all platforms.
