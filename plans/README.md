# Plans Workspace

This directory is the canonical home for active execution plans.

Rules:
- New plans go under `plans/<product-or-program>/...`.
- Keep a short README in each product folder with active priorities.
- If a plan is moved from another location, leave a pointer file at the old path.
- Do not create active plans in repo root or `docs/`.
- Use `docs/REPO_STRUCTURE_PROTOCOL.md` for full repo organization rules.
- Validate structure with: `python scripts/check_plan_structure_gate.py`.

Current product folders:
- `plans/thomas/`
