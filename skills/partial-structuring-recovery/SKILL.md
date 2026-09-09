---
name: partial-structuring-recovery
description: Implement partial_structure APIs, PartialResult value/is_complete, structured_fields, failed_fields, errors, error_map, refine, attrs/dataclasses/TypedDict, forbid_extra_keys, detailed_validation, defaults, nested fields, collections, and init=False recovery behavior.
---

# Partial Structuring Recovery

Use this skill when adding or fixing partial object structuring, partial deserialization, field-level recovery, or APIs that return incomplete-but-usable results after conversion failures.

## Workflow
1. Locate the public structure/deserialize API, exports, converter state, generated hooks, and type-specific paths before adding a parallel implementation.
2. Define the result contract first: partial value or `None`, complete flag, immutable successful field names, immutable failed field names, aggregate error, and field error map.
3. Classify each input field independently. Missing required fields fail; missing fields with defaults use fallback values; non-init fields stay out of structured and failed field sets.
4. Recurse through nested attrs classes, dataclasses, and TypedDicts. If a nested partial value exists but is incomplete, use it while marking the parent field failed.
5. Treat collection fields atomically unless the requested API explicitly supports per-element partials. Any element failure fails that collection field.
6. Preserve strictness controls such as extra-key rejection and detailed validation. Extra keys may make the result incomplete without discarding otherwise valid values when the contract requires recovery.
7. Implement refine/update by re-running only the failed field surface against new input, preserving previously structured fields and merging errors deterministically.
8. Add matrix tests for complete input, missing defaults, missing required fields, nested partial objects, collection element failure, TypedDict required/optional keys, `init=False`, extra keys, detailed validation, and refine.

## Rules
- Do not let fallback defaults count as structured input fields unless the contract explicitly says so.
- A required field failure should prevent constructing the parent value unless the type has a valid partial-construction path.
- Error maps should preserve the original field names users provided in the public API contract.
- Generated and handwritten structuring paths must agree on result shape and completeness semantics.
