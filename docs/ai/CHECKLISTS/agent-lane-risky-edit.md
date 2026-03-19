# Lane: risky-edit

- Use this lane for guarded paths, shared scope, release-sensitive work, or any change where a simple edit can cheat quality.
- Workboard awareness and claim discipline both matter here.
- Read:
  - `docs/ai/AGENT_ROUTER.md`
  - `docs/AGENT_FILE_EDITING_RULES.md`
  - `GUARDRAILS.md`
  - `AGENTS.md`
  - local module `GUARDRAILS.md` for touched paths
- Required checks:
  - run focused regression tests for changed behavior
  - run release hygiene checks when product behavior changes
  - validate workboard claim requirements if tracked work is required
- Required proof:
  - checks run
  - why the chosen runtime file is the live source of truth
- Escalate to a heavier lane when:
  - the task spans multiple subsystems
  - delegation or handoff becomes necessary