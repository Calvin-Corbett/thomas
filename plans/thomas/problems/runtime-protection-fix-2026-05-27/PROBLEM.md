# Task Problem Record: runtime-protection-fix-2026-05-27

- task_id: `runtime-protection-fix-2026-05-27`
- owner: `unassigned`
- status: `resolved`
- scope: `scripts,thomas`
- summary: close fs.write_file bypass of runtime/.runtime_protection_disabled flag via signed-content plus path protection
- created_at_utc: `2026-05-27T00:00:00+00:00`
- last_synced_at_utc: `2026-08-26T00:00:00+00:00`
- closure: accepted-risk:2026-08-26-runtime-protection-fix-2026-05-27-is-fixed-and-permanently-tested-thomas-tools-filesystem-py-252-266-always-protects-runtime-flag-rel-runtime-key-rel-44-44-protection-tests-green-but-no-red-path-cases-gate-covers-filesystem-tool-level-write-protection-of-the-runtime-protection-control-files-the-closure-grammar-has-no-form-for-a-fixed-and-permanently-tested-incident-that-a-gate-does-not-watch-1

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

## Closure (2026-08-26, phase-2 batch-2 verification)

- Re-verified fresh at HEAD: `thomas/tools/filesystem.py:252-266` checks
  `_RUNTIME_FLAG_REL`/`_RUNTIME_KEY_REL` BEFORE the disable-flag bypass logic
  runs, commented "Always-protected... must never be bypassed by the disable
  flag itself" -- any write to either path is refused unless routed through
  `_maybe_apply_native_auth_override` (line 261), which requires a live
  native-auth prompt (`thomas/tools/native_auth.py::request_native_authorization`).
  This is exactly the native-auth-gated behavior the Fix Plan asked for.
- Ran the full protection test cluster fresh:
  `tests/test_filesystem_protection_native_auth.py`,
  `test_filesystem_protection_adversarial.py`,
  `test_filesystem_protection_control_files.py`,
  `test_runtime_guard_signed_flag.py`,
  `test_native_auth_filesystem_guard.py` -> `44 passed in 4.08s` (0 failed).
- No RED_PATH_CASES gate covers this incident's class. RED_PATH_CASES
  (`tests/test_every_enforcing_gate_can_fail.py`) registers exactly six
  gates -- `monolith_guard.py`, `merge_resurrection_gate.py`,
  `dead_ref_gate.py`, `workboard_evidence_gate.py`, `problem_closure_gate.py`,
  `site_visual_proof.py` -- none of which check filesystem-tool-level write
  protection. `protected_files_gate.py` was the only plausible candidate by
  name and it guards a different class entirely (git-commit-time protection
  of GUARDRAILS.md/AGENTS.md/architecture-rule files, not `fs.write_file`
  tool-level protection of the runtime-protection control files); it is also
  not registered in RED_PATH_CASES. Citing it as `gate:protected_files_gate.py`
  would be a wrong-gate closure, not an honest one.
- This is the closure-grammar gap's second instance: the incident is fixed
  and permanently tested (guarded by runtime code plus a green, unchanging
  test suite), but a `test:` closure form does not exist -- tests are not a
  recognized closure form under `problem_closure_gate.py`. Closed under
  accepted risk
  `2026-08-26-runtime-protection-fix-2026-05-27-is-fixed-and-permanently-tested-thomas-tools-filesystem-py-252-266-always-protects-runtime-flag-rel-runtime-key-rel-44-44-protection-tests-green-but-no-red-path-cases-gate-covers-filesystem-tool-level-write-protection-of-the-runtime-protection-control-files-the-closure-grammar-has-no-form-for-a-fixed-and-permanently-tested-incident-that-a-gate-does-not-watch-1`
  (owner `calvin (standing delegation 2026-08-24, claude-recorded)`, expires
  2026-11-30) rather than under a gate citation. A `test:` closure form is a
  design candidate for the owner queue -- not built here.
