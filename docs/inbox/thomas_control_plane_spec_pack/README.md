# Thomas Control Plane Spec Pack

This zip contains:
- MEGA_PROMPT.txt: the one-shot “build the whole thing” prompt for your coding agent
- docs/CONTROLPLANE.md: architecture + design invariants
- docs/ROLLOUT_CHECKLIST.md: staged enablement checklist
- docs/INTEGRATION_REPORT_TEMPLATE.md: fill-in template after patch generation

Use:
1) Paste MEGA_PROMPT.txt into Codex/Gemini/your agent.
2) After it produces the patch zip, compare it against these docs.
3) Make the agent fill in INTEGRATION_REPORT_TEMPLATE.md based on what it actually changed.
