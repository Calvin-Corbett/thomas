---
name: skill-distillation
description: Recreate external skills into Thomas-native drafts from explicit local references without copying foreign code or long text verbatim.
---

# Skill Distillation

Use this skill when Thomas is reviewing an external skill or workflow and needs to draft a Thomas-native replacement from scratch.

## Workflow
1. Read the external source in a read-only way.
2. Extract intent, inputs, outputs, tools, constraints, risks, and examples.
3. Generate a fresh Thomas-native skill draft with its own wording and structure.
4. Run no-copy checks, validation, and review before promotion.
5. Promote only after the draft is reviewed and the provenance metadata is intact.

## Rules
- Distill from explicit local paths only.
- Do not copy foreign scripts, assets, or large text blocks into Thomas.
- Treat external skills as references, not installable payloads.