# Lane: ui-proof

- Use this lane when touching `apps/site/src/app/**` or `apps/site/src/components/**`.
- Visual proof is mandatory. This is not optional UI polish.
- Read:
  - `docs/ai/AGENT_ROUTER.md`
  - `AGENTS.md`
  - `skills/ui-precision-guard/SKILL.md`
- Required checks:
  - `python scripts/refresh_site_visual_proof.py`
  - `python scripts/check_site_visual_proof.py`
- Required proof:
  - updated proof JSON
  - updated screenshots, baselines, and diffs
- Escalate to a heavier lane when:
  - the UI task also becomes multi-agent
  - the UI task crosses into release-critical or architecture work