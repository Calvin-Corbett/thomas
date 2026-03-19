---
name: auto-skillify
description: Detect repeated multi-step workflows and turn them into reusable Thomas-native skill bundles with validation and maintenance notes.
---

# Auto Skillify

Use this skill when Thomas notices the same workflow being repeated and should capture it as a reusable Thomas-native skill.

## Workflow
1. Inspect the repeated workflow and confirm the trigger, inputs, outputs, and failure modes.
2. Extract the stable steps that are worth turning into a reusable skill.
3. Write a Thomas-native skill bundle with explicit scope, guardrails, and validation.
4. Check whether the new skill overlaps with an existing bundle before adding it.
5. Record why the skill exists and what should trigger it in future work.

## Rules
- Do not create duplicate skills for one-off tasks.
- Prefer refining existing Thomas skills over fragmenting the catalog.
