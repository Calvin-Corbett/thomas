### Changed

- **The agent execution loop is split into cohesive runtime modules — by Thomas.**
  Turn setup and context assembly now live in `thomas/agent/loop_execution_setup.py`;
  provider connection, compaction and rolling prompt-rate calculation live in
  `thomas/agent/loop_provider_runtime.py`. `thomas/agent/loop_execution.py` stays the
  import-compatible entry point and drops from 1034 to 790 lines, clearing the
  800-line soft limit and completing Phase 0a of the Praxis plan
  (`docs/superpowers/specs/2026-09-19-praxis-in-thomas-design.md` §11).

  This refactor was performed by a Thomas Build session, driven through the browser
  like any other user, not written by hand. Worth recording because it is the first
  time Thomas has restructured its own agent loop:
  - it chose the seams and wrote both modules;
  - it selected its own verification set (`test_agent_loop_monolith_contract`,
    `test_agent_loop_tool_policy`, `test_agent_loop_tool_exec`,
    `test_constraint_envelope`, `test_checkin_policy`, `test_hook_event_surface`);
  - it wrote `tests/test_loop_execution_split.py`, which pins the 800-line bound, and
    asserts the re-exported helpers are the *same objects* so every existing import
    path still resolves, and that the extracted symbols are reached by normal imports;
  - mid-run it introduced a real regression — `compact_conversation_if_needed() got an
    unexpected keyword argument 'preserve_last'` — and diagnosed and fixed it without
    being told;
  - it repaired its own `ruff` import-ordering finding on the next pass.

  Verified independently before landing: `ruff` clean on all three files, its own
  5 tests green, and its chosen set at 70 passed. One failure in
  `test_agent_loop_token_guard.py` was checked against the unsplit file on dev and
  fails there too, so it is not from this change.
