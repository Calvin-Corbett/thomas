---
name: serializer-deserializer-feature-matrix
description: Harden serializer, deserializer, schema, alias, field metadata, and generated-code changes with cross-feature regression matrices.
---

# Serializer Deserializer Feature Matrix

Use this skill when editing serialization, deserialization, schema generation, field metadata, aliases, generated pack/unpack code, or roundtrip behavior.

## Workflow
1. Identify every behavior axis touched by the change: alias, rename, prefix, omit-none, optional/default, nested object, unknown-key policy, collision handling, and roundtrip.
2. Build a small matrix that combines the changed axis with at least two existing axes; do not test only the happy path for the new option.
3. Add focused regression tests for mixed-axis behavior before finalizing. Include serialize, deserialize, and roundtrip checks when the code supports all three.
4. Run the new focused tests and one adjacent existing suite that exercises the same generated-code or adapter path.
5. Before handoff, state which axes were covered and which were intentionally out of scope.

## Rules
- A serializer fix is incomplete if it only proves the simplest field-name case.
- Alias and rename semantics must be tested by original field name and external key when both are supported.
- Optional and omit-none behavior must be tested for both present and absent child values.
- Collision and forbid-extra-key checks must remain active after flattening, prefixing, or renaming.
