---
name: skill-authoring
description: Design and refine Thomas-native skills with explicit workflows, validation rules, and small reusable bundles.
---

# Skill Authoring

Use this skill when Thomas needs to create or revise a first-party skill bundle under `skills/<name>/SKILL.md` or a user-owned Thomas skill under `~/.thomas/skills/`.

## Workflow
1. Inspect existing Thomas skills before adding a new one.
2. Define the trigger, scope boundaries, required tools, and failure modes.
3. Keep the bundle small and Thomas-native: prefer concise instructions over copied playbooks.
4. Add or update validation notes so the skill is testable.
5. If the skill changes product behavior, update docs and tests in the same pass.

## Rules
- Never copy another system's skill text verbatim.
- Prefer repo-native paths, commands, and guardrails.
- Keep first-party skills broadly reusable and free of user-specific secrets.