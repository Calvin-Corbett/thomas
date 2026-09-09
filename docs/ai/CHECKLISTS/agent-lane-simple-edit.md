# Lane: simple-edit

- Use this lane for a small isolated code or doc change with no claim conflict and no guarded UI path.
- Workboard awareness is required, but full claim/handoff flow is optional unless the router flags it.
- Read:
  - `docs/ai/AGENT_ROUTER.md`
  - `docs/AGENT_FILE_EDITING_RULES.md`
  - `GUARDRAILS.md`
  - local module `GUARDRAILS.md` for touched paths
- Required checks:
  - file-level compile or syntax check for edited code
  - focused regression test for changed behavior
- Required proof:
  - list the exact files changed and the checks run
- Escalate to a heavier lane when:
  - scope expands beyond a small isolated change
  - shared scope or active-claim conflict appears
  - release hygiene, architecture, or visual proof becomes required